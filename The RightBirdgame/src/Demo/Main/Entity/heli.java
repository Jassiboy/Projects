package Demo.Main.Entity;

import Demo.Main.Resources;

import javax.annotation.Resource;
import java.awt.*;

/**
 * Created by jassiboy on 2/27/2017.
 */
public class heli extends Entity {
    public heli(int xCord, int yCord) {
        super(xCord, yCord,180,135);
        this.xVel = -10;

    }

    @Override
    public Image getImage() {
        return Resources.heliImage;
    }
}
