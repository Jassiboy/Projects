package Demo.Main.Entity;

import Demo.Main.Resources;

import javax.annotation.Resource;
import java.awt.*;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class Log extends Entity {
    public Log(int xCord, int yCord) {

        super(xCord, yCord, 172, 127);
        this.xVel = -10;
    }

    @Override
    public Image getImage() {
        return Resources.logImage;
    }
}
