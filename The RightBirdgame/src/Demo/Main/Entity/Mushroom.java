package Demo.Main.Entity;

import Demo.Main.Resources;

import javax.annotation.Resource;
import java.awt.*;

/**
 * Created by jassiboy on 2/27/2017.
 */
public class Mushroom extends Entity{
    public Mushroom(int xCord, int yCord) {
        super(xCord, yCord, 224,100);
        this.xVel+=5;
    }

    @Override
    public Image getImage() {
        return Resources.mushroomImage;
    }
}
